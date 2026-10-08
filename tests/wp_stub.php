<?php
// Minimal stand-ins for the WordPress and WP-CLI functions publish.php uses,
// so the script can run in tests without a WordPress install.
$GLOBALS['meta'] = array(
	7178 => array(
		'_elementor_data'                    => array( '[old]' ),
		'_elementor_edit_mode'               => array( 'builder' ),
		'bauen_page_header_selector_opt'     => array( 'static' ),
		'bauen_page_full_img_header_bg_img'  => array( 'https://uniteideas.com/old.jpg' ),
		'bauen_wr_portfoliotype_container'   => array( serialize( array( 'a' => 'b\\c' ) ) ),
		'_aioseo_title'                      => array( 'Old SEO' ),
		'_thumbnail_id'                      => array( '7150' ),
		'_edit_lock'                         => array( '1:1' ),
	),
);
$GLOBALS['terms'] = array( 'architecture' => array( 'term_id' => '116' ) );
$GLOBALS['log'] = array();
class WP_CLI {
	static function error( $m ) { fwrite( STDERR, "ERROR: $m\n" ); exit( 1 ); }
	static function warning( $m ) { fwrite( STDERR, "WARN: $m\n" ); }
}
function get_post( $id ) { return 7178 === $id ? (object) array( 'post_type' => 'portfolio', 'post_author' => 1 ) : null; }
function wp_insert_post( $a, $e = false ) { $GLOBALS['log'][] = array( 'insert', $a ); return isset( $a['ID'] ) ? $a['ID'] : 9001; }
function wp_update_post( $a ) { $GLOBALS['log'][] = array( 'update', $a ); return $a['ID']; }
function is_wp_error( $x ) { return false; }
function get_post_meta( $id, $key = '', $single = false ) {
	$m = isset( $GLOBALS['meta'][ $id ] ) ? $GLOBALS['meta'][ $id ] : array();
	if ( '' === $key ) { return $m; }
	return isset( $m[ $key ] ) ? maybe_unserialize( $m[ $key ][0] ) : '';
}
function maybe_unserialize( $v ) { $u = @unserialize( $v ); return ( false !== $u || 'b:0;' === $v ) ? $u : $v; }
function wp_unslash( $v ) { return is_array( $v ) ? array_map( 'wp_unslash', $v ) : stripslashes( $v ); }
function wp_slash( $v ) { return is_array( $v ) ? array_map( 'wp_slash', $v ) : addslashes( $v ); }
function add_post_meta( $id, $k, $v ) { $GLOBALS['meta'][ $id ][ $k ][] = wp_unslash( $v ); }
function update_post_meta( $id, $k, $v ) { $GLOBALS['meta'][ $id ][ $k ] = array( wp_unslash( $v ) ); }
function set_post_thumbnail( $id, $t ) { $GLOBALS['meta'][ $id ]['_thumbnail_id'] = array( $t ); }
function wp_get_attachment_url( $id ) { return "https://uniteideas.com/new-$id.jpg"; }
function term_exists( $slug, $tax ) { return isset( $GLOBALS['terms'][ $slug ] ) ? $GLOBALS['terms'][ $slug ] : null; }
function wp_insert_term( $name, $tax, $args ) { $GLOBALS['log'][] = array( 'new_term', $name ); return $GLOBALS['terms'][ $args['slug'] ] = array( 'term_id' => '200' ); }
function wp_set_object_terms( $id, $ids, $tax ) { $GLOBALS['log'][] = array( 'terms', $ids, $tax ); }
function admin_url( $p ) { return "https://uniteideas.com/wp-admin/$p"; }
function get_preview_post_link( $id ) { return "https://uniteideas.com/?p=$id&preview=true"; }
function wp_json_encode( $v ) { return json_encode( $v ); }
register_shutdown_function( function () {
	fwrite( STDERR, json_encode( array( 'meta' => $GLOBALS['meta'][9001] ?? null, 'log' => $GLOBALS['log'] ) ) );
} );
