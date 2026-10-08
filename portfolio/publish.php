<?php
/**
 * Runs on the WordPress server through `wp eval-file -` (WP-CLI over SSH).
 * Creates a DRAFT portfolio post that copies the template post's settings,
 * with a new Elementor layout, featured image and categories.
 * The Python side replaces __PAYLOAD__ with base64-encoded JSON.
 */

$payload = json_decode( base64_decode( '__PAYLOAD__' ), true );
if ( ! is_array( $payload ) ) {
	WP_CLI::error( 'Payload could not be decoded.' );
}

$template_id = (int) $payload['template_id'];
$template    = get_post( $template_id );
if ( ! $template || 'portfolio' !== $template->post_type ) {
	WP_CLI::error( "Template post $template_id is not a portfolio post." );
}

$post_id = wp_insert_post(
	array(
		'post_type'    => 'portfolio',
		'post_status'  => 'draft',
		'post_title'   => $payload['title'],
		'post_name'    => $payload['slug'],
		'post_excerpt' => $payload['excerpt'],
		'post_author'  => (int) $template->post_author,
	),
	true
);
if ( is_wp_error( $post_id ) ) {
	WP_CLI::error( $post_id->get_error_message() );
}

// Copy the theme and Elementor page settings from the template. Skip the
// layout itself, caches, edit locks, SEO text and the featured image.
$skip_keys     = array(
	'_elementor_data',
	'_elementor_css',
	'_elementor_element_cache',
	'_elementor_page_assets',
	'_edit_lock',
	'_edit_last',
	'_thumbnail_id',
	'_wp_old_date',
	'_wp_old_slug',
);
$skip_prefixes = array( '_aioseo_', '_monsterinsights_' );

foreach ( get_post_meta( $template_id ) as $key => $values ) {
	if ( in_array( $key, $skip_keys, true ) ) {
		continue;
	}
	foreach ( $skip_prefixes as $prefix ) {
		if ( 0 === strpos( $key, $prefix ) ) {
			continue 2;
		}
	}
	foreach ( $values as $value ) {
		add_post_meta( $post_id, $key, wp_slash( maybe_unserialize( $value ) ) );
	}
}

// New layout. Elementor stores it as slashed JSON.
update_post_meta( $post_id, '_elementor_data', wp_slash( $payload['elementor_data'] ) );

// Featured image, which the theme also uses as the page banner.
$banner_id  = (int) $payload['banner_id'];
$banner_url = wp_get_attachment_url( $banner_id );
set_post_thumbnail( $post_id, $banner_id );

// If the template sets a banner image directly, point it at the new one.
$header_key = 'bauen_page_full_img_header_bg_img';
$header     = get_post_meta( $template_id, $header_key, true );
if ( '' !== $header && null !== $header ) {
	if ( is_numeric( $header ) ) {
		$new_header = $banner_id;
	} elseif ( is_array( $header ) ) {
		$new_header = $header;
		if ( isset( $new_header['id'] ) ) {
			$new_header['id'] = $banner_id;
		}
		if ( isset( $new_header['url'] ) ) {
			$new_header['url'] = $banner_url;
		}
	} else {
		$new_header = $banner_url;
	}
	update_post_meta( $post_id, $header_key, wp_slash( $new_header ) );
}

// Categories, creating any that do not exist yet (for example QSR).
$term_ids = array();
foreach ( $payload['categories'] as $category ) {
	$term = term_exists( $category['slug'], 'portfolio_category' );
	if ( ! $term ) {
		$term = wp_insert_term( $category['name'], 'portfolio_category', array( 'slug' => $category['slug'] ) );
	}
	if ( is_wp_error( $term ) ) {
		WP_CLI::warning( 'Category ' . $category['name'] . ': ' . $term->get_error_message() );
		continue;
	}
	$term_ids[] = (int) $term['term_id'];
}
if ( $term_ids ) {
	wp_set_object_terms( $post_id, $term_ids, 'portfolio_category' );
}

// Attach the uploaded images to the new post.
foreach ( $payload['attachment_ids'] as $attachment_id ) {
	wp_update_post(
		array(
			'ID'          => (int) $attachment_id,
			'post_parent' => $post_id,
		)
	);
}

// Make Elementor rebuild its CSS for the new layout.
if ( class_exists( '\Elementor\Plugin' ) ) {
	\Elementor\Plugin::$instance->files_manager->clear_cache();
}

echo wp_json_encode(
	array(
		'post_id'      => $post_id,
		'edit_url'     => admin_url( "post.php?post=$post_id&action=elementor" ),
		'preview_url'  => get_preview_post_link( $post_id ),
	)
) . "\n";
